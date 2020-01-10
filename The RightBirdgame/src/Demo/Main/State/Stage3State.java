package Demo.Main.State;

import Demo.Main.Entity.*;
import Demo.Main.GamePanel;
import Demo.Main.RandomGenerator;
import Demo.Main.Resources;

import java.awt.*;
import java.awt.event.KeyEvent;
import java.util.ArrayList;

/**
 * Created by jassiboy on 3/5/2017.
 */
public class Stage3State extends State {
    private int logsCrossed = 0;
    private int background3ImageXcord = 0;
    private java.util.List<heli> helis;
    private java.util.List<Grass> grasses;
    public Dragon dragon;
    private java.util.List<Fireboll> firebolls;
    private java.util.List<Entity> entities;

    public Stage3State() {

        super();
        helis = new ArrayList<>();
        grasses = new ArrayList<>();
        entities = new ArrayList<>();
        firebolls = new ArrayList<>();

        helis.add(new heli(900, 55));
        helis.add(new heli(900, 355));
        grasses.add(new Grass(1, 490));
        grasses.add(new Grass(370, 490));
        grasses.add(new Grass(740, 490));
        grasses.add(new Grass(1110, 490));
        dragon = new Dragon(200, 50);

        entities.addAll(helis);
        entities.addAll(grasses);
        entities.add(dragon);
    }

    @Override
    public void update() {
        for (Entity e : entities) {
            e.update();
        }
        background3ImageXcord -= 10;
        for (Grass g : grasses) {
            if (g.xCord > 930) {
                g.xCord = -210;
            }
//            if(bird.isColldingWith(m)) {
//                bird.yVel =- 80;
//                bird.yAcc =9;
//            }
        }

        for (heli b : helis) {
            if (b.xCord < -20) {
                b.xCord = 980;

                if (RandomGenerator.getInt(0, 4) == 0) {
                    b.yCord = 55;
                } else if (RandomGenerator.getInt(0, 5) == 1)
                    b.yCord = 155;
                else if (RandomGenerator.getInt(0, 5) == 2)
                    b.yCord = 285;
                else {
                    b.yCord = 370;
                }


                if (b.visible) {
                    logsCrossed++;

                    if (logsCrossed == 3) {
                        GamePanel.currentState = new Endstage();
                    }
                }

                b.visible = true;

            }

            if (dragon.isColldingWith(b)) {
                dragon.xCord -= 20;
                b.visible = false;
                Resources.flapAudio.play();

            }

            if (background3ImageXcord == -1000)
                background3ImageXcord = 0;
        }

        if (dragon.yCord < 0) {
            dragon.yCord = 0;
            dragon.yVel = 26;
            dragon.yAcc = 0;
        }


    }

    @Override
    public void render(Graphics g) {
        g.drawImage(Resources.Stage3Image, background3ImageXcord, 0, null);
        g.drawImage(Resources.Stage3Image, background3ImageXcord + 1000, 0, null);

        for (Entity e : entities) {
            if (e.visible) {
                g.drawImage(e.getImage(), e.xCord, e.yCord, null);
            }
        }
//
//       fireboll.update();
//
//       g.drawImage(Resources.firebollImage,dragon.xCord+138,dragon.yCord,null);
//}
    }

    @Override
    public void onKeyPressed(int pressedKeyCode) {
        if (pressedKeyCode == KeyEvent.VK_UP) {
            dragon.yVel = -26;
            dragon.yAcc = 2;
        } else if (pressedKeyCode == KeyEvent.VK_DOWN) {
            //bird.duck(true);
            dragon.yVel = 26;
            dragon.yAcc = 2;
        } else if (pressedKeyCode == KeyEvent.VK_SPACE) {
            dragon.attack(true);

            entities.add(new Fireboll(dragon.xCord + 138, dragon.yCord));

        }
    }

}

