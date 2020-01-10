package Demo.Main.Entity;

import Demo.Main.Resources;

import javax.annotation.Resource;
import java.awt.*;

/**
 * Created by jassiboy on 3/5/2017.
 */
public class Grass extends Entity {
    public Grass(int xCord, int yCord) {
        super(xCord, yCord, 370,104);
        this.xVel+=5;
    }

    @Override
    public Image getImage() {
        return Resources.grassImage;
    }
}
