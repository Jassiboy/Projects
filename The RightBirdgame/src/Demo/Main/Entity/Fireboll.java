package Demo.Main.Entity;

import Demo.Main.Resources;

import java.awt.*;

/**
 * Created by jassiboy on 3/5/2017.
 */
public class Fireboll extends Entity {
    public Fireboll(int xCord, int yCord) {
        super(xCord, yCord, 138,138);
        this.xVel=15;

    }



    @Override
    public Image getImage() {
        return Resources.firebollImage;
    }
}
